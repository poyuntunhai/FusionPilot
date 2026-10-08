package com.fusionpilot.backend.simulation;

public class SimulationCancelledException extends RuntimeException {
    public SimulationCancelledException() {
        super("Simulation was cancelled by the user");
    }
}
