package com.sirs.interceptor;

import com.sirs.util.JwtUtil;
import io.jsonwebtoken.Claims;
import io.jsonwebtoken.ExpiredJwtException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.HandlerInterceptor;

@Component
public class AuthInterceptor implements HandlerInterceptor {

    private static final Logger log = LoggerFactory.getLogger(AuthInterceptor.class);
    private final JwtUtil jwtUtil;

    public AuthInterceptor(JwtUtil jwtUtil) {
        this.jwtUtil = jwtUtil;
    }

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response,
                             Object handler) throws Exception {
        if ("OPTIONS".equalsIgnoreCase(request.getMethod())) {
            return true;
        }

        String header = request.getHeader("Authorization");
        if (header == null || !header.startsWith("Bearer ")) {
            sendError(response, 1003, "未登录或 Token 已过期");
            return false;
        }

        String token = header.substring(7);
        try {
            Claims claims = jwtUtil.parseToken(token);
            request.setAttribute("userId", Long.valueOf(claims.getSubject()));
            request.setAttribute("username", claims.get("username"));
            return true;
        } catch (ExpiredJwtException e) {
            sendError(response, 1003, "未登录或 Token 已过期");
            return false;
        } catch (Exception e) {
            log.warn("Token parse error: {}", e.getMessage());
            sendError(response, 1003, "未登录或 Token 已过期");
            return false;
        }
    }

    private void sendError(HttpServletResponse response, int code, String msg) throws Exception {
        response.setContentType("application/json;charset=UTF-8");
        response.setStatus(200);
        response.getWriter().write(
            String.format("{\"code\":%d,\"msg\":\"%s\",\"data\":null,\"timestamp\":%d}",
                code, msg, System.currentTimeMillis() / 1000)
        );
    }
}
