package com.fusionpilot.backend.observation;

import com.fusionpilot.backend.scenario.ObservationSourceConfig;

import java.util.Random;

public interface ObservationSource {
    ObservationSourceResult observe(
            TargetState target,
            int timeStep,
            ObservationSourceConfig config,
            Random random
    );
}