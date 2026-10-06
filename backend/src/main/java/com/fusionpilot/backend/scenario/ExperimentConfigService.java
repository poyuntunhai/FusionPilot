package com.fusionpilot.backend.scenario;

import org.springframework.stereotype.Service;

import java.util.List;

@Service
public class ExperimentConfigService {

    public ExperimentConfig defaultConfig() {
        return new ExperimentConfig(
                "multi-target-demo",
                3,
                100,
                1.0,
                2,
                FusionMethod.WEIGHTED_AVERAGE,
                SchedulingPolicy.ROUND_ROBIN,
                20260928L,
                List.of(
                        new ObservationSourceConfig(
                                ObservationSourceType.RADAR,
                                3.0,
                                0.05,
                                0,
                                0.90
                        ),
                        new ObservationSourceConfig(
                                ObservationSourceType.EO_IR,
                                5.0,
                                0.15,
                                1,
                                0.75
                        ),
                        new ObservationSourceConfig(
                                ObservationSourceType.PRIOR_KNOWLEDGE,
                                8.0,
                                0.25,
                                0,
                                0.55
                        )
                )
        );
    }
}