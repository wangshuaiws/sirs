package com.sirs.controller;

import com.sirs.dto.Result;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.web.bind.annotation.*;

import java.nio.channels.Channel;

@RestController
@RequestMapping("/api/drawings")
public class DrawingController {

    private final StringRedisTemplate redis;
    private static final String KEY_PREFIX = "drawings:";

    public DrawingController(StringRedisTemplate redis) {
        this.redis = redis;
    }

    private Long getUserId(HttpServletRequest request) {
        return (Long) request.getAttribute("userId");
    }

    @GetMapping("/{stockCode}")
    public Result<String> get(@PathVariable String stockCode, HttpServletRequest request) {
        String key = KEY_PREFIX + getUserId(request) + ":" + stockCode;
        String json = redis.opsForValue().get(key);
        return Result.success(json != null ? json : "[]");
    }

    @PutMapping("/{stockCode}")
    public Result<Void> save(@PathVariable String stockCode,
                             @RequestBody String drawingsJson,
                             HttpServletRequest request) {
        String key = KEY_PREFIX + getUserId(request) + ":" + stockCode;
        redis.opsForValue().set(key, drawingsJson);
        return Result.success();
    }

    @DeleteMapping("/{stockCode}")
    public Result<Void> delete(@PathVariable String stockCode, HttpServletRequest request) {
        String key = KEY_PREFIX + getUserId(request) + ":" + stockCode;
        redis.delete(key);
        return Result.success();
    }
}
