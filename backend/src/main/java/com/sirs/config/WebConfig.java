package com.sirs.config;

import com.sirs.interceptor.AuthInterceptor;
import com.sirs.interceptor.RateLimitInterceptor;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

@Configuration
public class WebConfig implements WebMvcConfigurer {

    private final AuthInterceptor authInterceptor;
    private final RateLimitInterceptor rateLimitInterceptor;

    public WebConfig(AuthInterceptor authInterceptor, RateLimitInterceptor rateLimitInterceptor) {
        this.authInterceptor = authInterceptor;
        this.rateLimitInterceptor = rateLimitInterceptor;
    }

    @Override
    public void addInterceptors(InterceptorRegistry registry) {
        // 注册限流 — 仅 /api/auth/register
        registry.addInterceptor(rateLimitInterceptor)
                .addPathPatterns("/api/auth/register");

        // 鉴权 — /api/groups/** 和 /api/notifications/**
        registry.addInterceptor(authInterceptor)
                .addPathPatterns("/api/groups/**")
                .addPathPatterns("/api/notifications/**");
    }
}
