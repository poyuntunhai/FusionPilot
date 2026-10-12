package com.fusionpilot.backend.dataset;

/** Raised when a configuration names a dataset that cannot be used as a truth source. */
public class DatasetNotUsableException extends RuntimeException {

    public DatasetNotUsableException(String message) {
        super(message);
    }
}
