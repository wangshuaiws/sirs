package com.sirs.dto;

import lombok.AllArgsConstructor;
import lombok.Data;

@Data
@AllArgsConstructor
public class Result<T> {
    private int code;
    private String msg;
    private T data;
    private long timestamp;

    public static <T> Result<T> success(T data) {
        return new Result<>(0, "success", data, System.currentTimeMillis() / 1000);
    }

    public static <T> Result<T> success() {
        return success(null);
    }

    public static <T> Result<T> error(int code, String msg) {
        return new Result<>(code, msg, null, System.currentTimeMillis() / 1000);
    }
}
