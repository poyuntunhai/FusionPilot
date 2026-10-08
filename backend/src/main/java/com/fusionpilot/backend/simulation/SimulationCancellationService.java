package com.fusionpilot.backend.simulation;

import org.springframework.stereotype.Service;

import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;

@Service
public class SimulationCancellationService {

    private final Set<Long> cancelledUsers = ConcurrentHashMap.newKeySet();

    public void start(long userId) {
        cancelledUsers.remove(userId);
    }

    public void cancel(long userId) {
        cancelledUsers.add(userId);
    }

    public boolean isCancelled(long userId) {
        return cancelledUsers.contains(userId);
    }

    public void clear(long userId) {
        cancelledUsers.remove(userId);
    }
}
