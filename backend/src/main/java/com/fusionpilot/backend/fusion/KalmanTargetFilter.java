package com.fusionpilot.backend.fusion;

/**
 * Constant-velocity Kalman filter over the 4-state vector {@code [x, y, vx, vy]}.
 *
 * <p>Model assumptions, chosen explicitly because the project rules require every simulation
 * fact to be traceable:</p>
 * <ul>
 *   <li><b>Process model</b> — discrete white-noise acceleration with standard deviation
 *       {@link #PROCESS_NOISE_ACCELERATION}. Targets in this scenario fly straight, so a small
 *       maneuver budget is enough for the filter to track them without lagging.</li>
 *   <li><b>Measurement model</b> — position-only, isotropic, with the per-source noise declared
 *       in the experiment configuration.</li>
 *   <li><b>Initialisation</b> — position from the first available measurement, velocity unknown
 *       (zero mean, {@link #INITIAL_VELOCITY_VARIANCE}). The filter therefore has to <i>earn</i>
 *       its velocity estimate instead of being handed the true one.</li>
 * </ul>
 *
 * <p>One instance exists per target per simulation run, owned by {@link FusionContext}.</p>
 */
final class KalmanTargetFilter {

    /**
     * Maneuver acceleration standard deviation in units per second squared.
     *
     * <p>An explicit assumption, not a derived quantity. The scenario targets fly perfectly
     * straight, so this is deliberately small: it only has to absorb the numerical drift a real
     * runway of measurements would never produce. Raise it if the targets are given manoeuvres,
     * otherwise the filter will lag a turning target.</p>
     *
     * <p>How it was chosen: the velocity estimate never settles when this is comparable to the
     * target speed, because the filter then reads measurement noise as acceleration. At 0.1 the
     * velocity estimate holds steady while position tracking stays at its best-in-class error.</p>
     */
    static final double PROCESS_NOISE_ACCELERATION = 0.1;

    /** Prior velocity variance (units/s)^2 when no velocity information exists yet. */
    static final double INITIAL_VELOCITY_VARIANCE = 400.0;

    private final double[] state = new double[4];
    private double[][] covariance = new double[4][4];
    private boolean seeded;

    boolean isSeeded() {
        return seeded;
    }

    /** Adopt a first measurement as the initial position belief. */
    void seed(double measurementX, double measurementY, double measurementNoise) {
        state[0] = measurementX;
        state[1] = measurementY;
        state[2] = 0.0;
        state[3] = 0.0;
        covariance = new double[4][4];
        covariance[0][0] = measurementNoise * measurementNoise;
        covariance[1][1] = measurementNoise * measurementNoise;
        covariance[2][2] = INITIAL_VELOCITY_VARIANCE;
        covariance[3][3] = INITIAL_VELOCITY_VARIANCE;
        seeded = true;
    }

    /** Time update: propagate state and covariance forward by {@code deltaSeconds}. */
    void predict(double deltaSeconds) {
        state[0] += state[2] * deltaSeconds;
        state[1] += state[3] * deltaSeconds;

        double[][] transition = {
                {1.0, 0.0, deltaSeconds, 0.0},
                {0.0, 1.0, 0.0, deltaSeconds},
                {0.0, 0.0, 1.0, 0.0},
                {0.0, 0.0, 0.0, 1.0}
        };
        covariance = add(
                multiply(multiply(transition, covariance), transpose(transition)),
                processNoise(deltaSeconds)
        );
    }

    /** Measurement update with a position-only observation of the given noise level. */
    void update(double measurementX, double measurementY, double measurementNoise) {
        double r = measurementNoise * measurementNoise;

        // Innovation covariance S = H P Hᵀ + R, where H selects the position block.
        double s00 = covariance[0][0] + r;
        double s01 = covariance[0][1];
        double s10 = covariance[1][0];
        double s11 = covariance[1][1] + r;
        double determinant = s00 * s11 - s01 * s10;
        if (Math.abs(determinant) < 1e-12) {
            return;
        }

        // Kalman gain K = P Hᵀ S⁻¹. Only the two position columns of P participate.
        double inverse00 = s11 / determinant;
        double inverse01 = -s01 / determinant;
        double inverse10 = -s10 / determinant;
        double inverse11 = s00 / determinant;

        double[] gainPosition = new double[4];
        double[] gainOther = new double[4];
        for (int row = 0; row < 4; row++) {
            gainPosition[row] = covariance[row][0] * inverse00 + covariance[row][1] * inverse10;
            gainOther[row] = covariance[row][0] * inverse01 + covariance[row][1] * inverse11;
        }

        double innovationX = measurementX - state[0];
        double innovationY = measurementY - state[1];
        for (int row = 0; row < 4; row++) {
            state[row] += gainPosition[row] * innovationX + gainOther[row] * innovationY;
        }

        // Covariance update P = (I - K H) P.
        double[][] next = new double[4][4];
        for (int row = 0; row < 4; row++) {
            for (int column = 0; column < 4; column++) {
                next[row][column] = covariance[row][column]
                        - gainPosition[row] * covariance[0][column]
                        - gainOther[row] * covariance[1][column];
            }
        }
        covariance = next;
    }

    double x() {
        return state[0];
    }

    double y() {
        return state[1];
    }

    double velocityX() {
        return state[2];
    }

    double velocityY() {
        return state[3];
    }

    /** Combined horizontal position standard deviation, used as the fusion uncertainty. */
    double positionUncertainty() {
        return Math.sqrt(Math.max(0.0, covariance[0][0] + covariance[1][1]));
    }

    private double[][] processNoise(double deltaSeconds) {
        double q = PROCESS_NOISE_ACCELERATION * PROCESS_NOISE_ACCELERATION;
        double dt2 = deltaSeconds * deltaSeconds;
        double dt3 = dt2 * deltaSeconds;
        double dt4 = dt3 * deltaSeconds;
        double[][] noise = new double[4][4];
        noise[0][0] = q * dt4 / 4.0;
        noise[1][1] = q * dt4 / 4.0;
        noise[0][2] = q * dt3 / 2.0;
        noise[2][0] = q * dt3 / 2.0;
        noise[1][3] = q * dt3 / 2.0;
        noise[3][1] = q * dt3 / 2.0;
        noise[2][2] = q * dt2;
        noise[3][3] = q * dt2;
        return noise;
    }

    private static double[][] multiply(double[][] left, double[][] right) {
        int rows = left.length;
        int shared = right.length;
        int columns = right[0].length;
        double[][] product = new double[rows][columns];
        for (int row = 0; row < rows; row++) {
            for (int column = 0; column < columns; column++) {
                double sum = 0.0;
                for (int index = 0; index < shared; index++) {
                    sum += left[row][index] * right[index][column];
                }
                product[row][column] = sum;
            }
        }
        return product;
    }

    private static double[][] transpose(double[][] matrix) {
        int rows = matrix.length;
        int columns = matrix[0].length;
        double[][] transposed = new double[columns][rows];
        for (int row = 0; row < rows; row++) {
            for (int column = 0; column < columns; column++) {
                transposed[column][row] = matrix[row][column];
            }
        }
        return transposed;
    }

    private static double[][] add(double[][] left, double[][] right) {
        double[][] sum = new double[left.length][left[0].length];
        for (int row = 0; row < left.length; row++) {
            for (int column = 0; column < left[row].length; column++) {
                sum[row][column] = left[row][column] + right[row][column];
            }
        }
        return sum;
    }
}
