package com.fusionpilot.backend.dataset;

import com.fusionpilot.backend.observation.TargetState;
import org.springframework.stereotype.Service;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

/**
 * Reads a stored dataset's ground truth and hands it to the simulation.
 *
 * <p>Import used to be the end of the road for a dataset — it was validated, filed, and never read
 * again, so "upload your own scene" stopped at "upload". This closes that: the truth in the package
 * becomes the scene the simulation runs on, replacing the synthesised trajectories in
 * {@code ObservationService}.
 *
 * <p>Only {@code truth.csv} is used here. The package's {@code observations.csv} is left alone on
 * purpose: observations stay generated from the configuration's sources, so the delay, noise and
 * dropout settings keep meaning what they say, and the same uploaded truth can be replayed under
 * different observation setups. (Lifting the recorded observations in as well is a larger change
 * with its own semantics — what a sensor "should have" reported is a different question from what
 * it did report.)
 *
 * <p><strong>Velocity is reconstructed, not read.</strong> {@code truth.csv} carries positions
 * only, and the fusion strategies want velocities, so they are differenced from neighbouring steps.
 */
@Service
public class DatasetTruthSource {

    /** Parsed truth is held in memory, so only a few datasets are kept — a busy box must not grow. */
    private static final int MAX_CACHED_DATASETS = 4;

    private final DatasetRepository repository;

    private final Map<String, DatasetTruth> cache = new LinkedHashMap<>(8, 0.75f, true) {
        @Override
        protected boolean removeEldestEntry(Map.Entry<String, DatasetTruth> eldest) {
            return size() > MAX_CACHED_DATASETS;
        }
    };

    public DatasetTruthSource(DatasetRepository repository) {
        this.repository = repository;
    }

    /** Parse (or reuse) the truth for a dataset. Throws if the dataset cannot serve as truth. */
    public synchronized DatasetTruth load(String datasetId) {
        DatasetTruth cached = cache.get(datasetId);
        if (cached != null) {
            return cached;
        }
        DatasetTruth loaded = parse(datasetId);
        cache.put(datasetId, loaded);
        return loaded;
    }

    private DatasetTruth parse(String datasetId) {
        DatasetRepository.DatasetRecord record = repository.findById(datasetId);
        if (record == null) {
            throw new DatasetNotUsableException("数据集不存在：" + datasetId);
        }
        if (!record.isRunnableAsTruth()) {
            String why = "VALIDATED".equals(record.status())
                    ? "它没有 truth.csv，只有观测，无法作为真值"
                    : "它没有通过校验";
            throw new DatasetNotUsableException(
                    "数据集「" + record.fileName() + "」不能用作真值：" + why + "。");
        }

        Path zipPath = Path.of(record.storagePath());
        if (!Files.isReadable(zipPath)) {
            // The row survived a lost file — say so rather than throwing a bare NoSuchFileException.
            throw new DatasetNotUsableException(
                    "数据集「" + record.fileName() + "」的文件已不在服务器上，请重新上传。");
        }

        try (ZipInputStream zip = new ZipInputStream(
                Files.newInputStream(zipPath), StandardCharsets.UTF_8)) {
            ZipEntry entry;
            while ((entry = zip.getNextEntry()) != null) {
                String name = Path.of(entry.getName()).getFileName().toString();
                if ("truth.csv".equals(name)) {
                    return parseTruth(new BufferedReader(new InputStreamReader(zip, StandardCharsets.UTF_8)));
                }
            }
        } catch (IOException exception) {
            throw new UncheckedIOException("读取数据集失败：" + datasetId, exception);
        }
        throw new DatasetNotUsableException("数据集「" + record.fileName() + "」的包里没有 truth.csv。");
    }

    /**
     * Parse a {@code truth.csv} stream.
     *
     * <p>Package-private and free of the repository on purpose: this is the part with the
     * arithmetic and the edge cases, and it should be testable from a string rather than only
     * through a database, a zip and a running server.
     */
    static DatasetTruth parseTruth(BufferedReader reader) throws IOException {
        String header = reader.readLine();
        if (header == null) {
            throw new DatasetNotUsableException("truth.csv 是空的。");
        }
        // Column order is looked up rather than assumed: import validated the presence of required
        // columns, not their order, so a package with them reordered is still legal.
        Map<String, Integer> columns = indexOf(header);
        int stepColumn = require(columns, "time_step");
        int targetColumn = require(columns, "target_id");
        int xColumn = require(columns, "x");
        int yColumn = require(columns, "y");

        Map<Integer, Map<Integer, double[]>> positionsByTarget = new TreeMap<>();
        int maxStep = -1;
        String line;
        while ((line = reader.readLine()) != null) {
            if (line.isBlank()) {
                continue;
            }
            String[] parts = line.split(",", -1);
            try {
                int step = Integer.parseInt(parts[stepColumn].trim());
                int targetId = Integer.parseInt(parts[targetColumn].trim());
                double x = Double.parseDouble(parts[xColumn].trim());
                double y = Double.parseDouble(parts[yColumn].trim());
                positionsByTarget.computeIfAbsent(targetId, key -> new HashMap<>()).put(step, new double[] {x, y});
                maxStep = Math.max(maxStep, step);
            } catch (ArrayIndexOutOfBoundsException | NumberFormatException exception) {
                throw new DatasetNotUsableException("truth.csv 有无法解析的行：" + line);
            }
        }
        if (positionsByTarget.isEmpty()) {
            throw new DatasetNotUsableException("truth.csv 里没有数据行。");
        }

        List<Integer> targetIds = new ArrayList<>(positionsByTarget.keySet());
        int stepCount = maxStep + 1;
        List<List<double[]>> byStep = new ArrayList<>(stepCount);
        double[][] previous = null;
        for (int step = 0; step < stepCount; step++) {
            List<double[]> row = new ArrayList<>(targetIds.size());
            for (int index = 0; index < targetIds.size(); index++) {
                double[] position = positionsByTarget.get(targetIds.get(index)).get(step);
                if (position == null) {
                    // A gap is filled from the last known position rather than dropped: dropping it
                    // would silently renumber the targets and change what "target 2" means mid-run.
                    position = previous == null ? new double[] {0.0, 0.0} : previous[index];
                }
                row.add(position);
            }
            byStep.add(row);
            previous = row.toArray(new double[0][]);
        }
        return new DatasetTruth(List.copyOf(targetIds), List.copyOf(byStep));
    }

    private static Map<String, Integer> indexOf(String header) {
        Map<String, Integer> columns = new HashMap<>();
        String[] names = header.split(",", -1);
        for (int index = 0; index < names.length; index++) {
            columns.put(names[index].trim(), index);
        }
        return columns;
    }

    private static int require(Map<String, Integer> columns, String name) {
        Integer index = columns.get(name);
        if (index == null) {
            throw new DatasetNotUsableException("truth.csv 缺少列：" + name);
        }
        return index;
    }

    /**
     * The parsed truth: one row of positions per time step, in a stable target order.
     *
     * <p>Positions are stored, velocities are computed on read, because velocity depends on the
     * configuration's {@code timeStepSeconds} and a dataset must survive being run at a different
     * step duration than the one it was recorded with.
     */
    public record DatasetTruth(List<Integer> targetIds, List<List<double[]>> positionsByStep) {

        public int targetCount() {
            return targetIds.size();
        }

        public int stepCount() {
            return positionsByStep.size();
        }

        /** Refuse a configuration this dataset cannot serve, before a run starts rather than during. */
        public void validateFor(int configuredTargetCount, int configuredSteps) {
            if (targetCount() != configuredTargetCount) {
                throw new DatasetNotUsableException(
                        "数据集里有 " + targetCount() + " 个目标，而配置里是 " + configuredTargetCount
                                + " 个；用数据集跑仿真时两者必须一致。");
            }
            if (stepCount() < configuredSteps) {
                throw new DatasetNotUsableException(
                        "数据集只有 " + stepCount() + " 个时间步，而配置要跑 " + configuredSteps
                                + " 步；请把步数改小，或换一个更长的数据集。");
            }
        }

        public List<TargetState> statesAt(int timeStep, double timeStepSeconds) {
            List<double[]> row = positionsByStep.get(timeStep);
            List<TargetState> states = new ArrayList<>(targetCount());
            for (int index = 0; index < targetCount(); index++) {
                double[] here = row.get(index);
                double[] before = timeStep > 0 ? positionsByStep.get(timeStep - 1).get(index) : here;
                double[] after = timeStep < stepCount() - 1 ? positionsByStep.get(timeStep + 1).get(index) : here;
                // Central difference in the interior, one-sided at the ends, zero for a single step.
                double span = (before == here ? 0 : 1) + (after == here ? 0 : 1);
                double velocityX = span == 0 ? 0.0 : (after[0] - before[0]) / (span * timeStepSeconds);
                double velocityY = span == 0 ? 0.0 : (after[1] - before[1]) / (span * timeStepSeconds);
                states.add(new TargetState(
                        targetIds.get(index),
                        here[0],
                        here[1],
                        velocityX,
                        velocityY,
                        timeStep
                ));
            }
            return states;
        }
    }
}
