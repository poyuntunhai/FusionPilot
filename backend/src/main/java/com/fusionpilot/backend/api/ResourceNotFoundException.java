package com.fusionpilot.backend.api;

/**
 * Signals that the addressed resource does not exist, so the API can answer 404 instead of
 * falling through to the generic 500 handler. Used for lookups of runs that were evicted from
 * history, deleted, or simply never existed.
 */
public class ResourceNotFoundException extends RuntimeException {

    public ResourceNotFoundException(String message) {
        super(message);
    }
}
