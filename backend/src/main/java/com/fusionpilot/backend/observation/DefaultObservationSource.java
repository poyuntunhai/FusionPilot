package com.fusionpilot.backend.observation;

import com.fusionpilot.backend.scenario.ObservationSourceConfig;
import com.fusionpilot.backend.scenario.ObservationSourceType;
import org.springframework.stereotype.Component;

import java.util.Random;

@Component
public class DefaultObservationSource implements ObservationSource {

    @Override
    public ObservationSourceResult observe(
            TargetState target,
            int timeStep,
            ObservationSourceConfig config,
            Random random
    ) {
        if (random.nextDouble() < config.missingRate()) {
            return new ObservationSourceResult(
                    target.x(),
                    target.y(),
                    0.0,
                    false
            );
        }

        double noiseScale = config.noiseStdDev();
        double x = target.x() + random.nextGaussian() * noiseScale;
        double y = target.y() + random.nextGaussian() * noiseScale;
        double confidence = Math.max(0.0, Math.min(1.0, config.confidence()));

        if (config.type() == ObservationSourceType.PRIOR_KNOWLEDGE) {
            confidence *= 0.8;
        }

        return new ObservationSourceResult(x, y, confidence, true);
    }
}