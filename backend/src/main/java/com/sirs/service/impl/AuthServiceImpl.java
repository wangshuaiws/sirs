package com.sirs.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.sirs.dto.*;
import com.sirs.entity.User;
import com.sirs.mapper.UserMapper;
import com.sirs.service.AuthService;
import com.sirs.service.GroupService;
import com.sirs.util.JwtUtil;
import com.wf.captcha.SpecCaptcha;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;
import org.springframework.util.DigestUtils;

import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Base64;
import java.util.UUID;

@Service
public class AuthServiceImpl implements AuthService {

    private static final Logger log = LoggerFactory.getLogger(AuthServiceImpl.class);
    private static final String CAPTCHA_PREFIX = "captcha:";
    private static final Duration CAPTCHA_TTL = Duration.ofMinutes(5);

    private final UserMapper userMapper;
    private final JwtUtil jwtUtil;
    private final StringRedisTemplate redis;
    private final GroupService groupService;

    public AuthServiceImpl(UserMapper userMapper, JwtUtil jwtUtil, StringRedisTemplate redis,
                           GroupService groupService) {
        this.userMapper = userMapper;
        this.jwtUtil = jwtUtil;
        this.redis = redis;
        this.groupService = groupService;
    }

    @Override
    public CaptchaResponse generateCaptcha() {
        SpecCaptcha captcha = new SpecCaptcha(130, 48, 4);
        String captchaId = UUID.randomUUID().toString();
        String code = captcha.text().toLowerCase();

        redis.opsForValue().set(CAPTCHA_PREFIX + captchaId, code, CAPTCHA_TTL);

        String base64 = "data:image/png;base64," +
                Base64.getEncoder().encodeToString(captcha.toBase64().getBytes(StandardCharsets.UTF_8));

        log.debug("Generated captcha: id={}, code={}", captchaId, code);
        return new CaptchaResponse(captchaId, base64);
    }

    @Override
    public LoginResponse register(RegisterRequest req) {
        // 1. 校验验证码
        String redisCode = redis.opsForValue().get(CAPTCHA_PREFIX + req.getCaptchaId());
        if (redisCode == null) {
            throw new BusinessException(ErrorCode.CAPTCHA_ERROR, "验证码已过期");
        }
        if (!redisCode.equals(req.getCaptchaCode().toLowerCase())) {
            throw new BusinessException(ErrorCode.CAPTCHA_ERROR, "验证码错误");
        }
        redis.delete(CAPTCHA_PREFIX + req.getCaptchaId());

        // 2. 校验用户名唯一
        Long count = userMapper.selectCount(
                new LambdaQueryWrapper<User>().eq(User::getUsername, req.getUsername()));
        if (count > 0) {
            throw new BusinessException(ErrorCode.USERNAME_EXISTS, "用户名已存在");
        }

        // 3. BCrypt 加密 + 入库
        User user = new User();
        user.setUsername(req.getUsername());
        user.setPasswordHash(hashPassword(req.getPassword()));
        user.setStatus(1);
        userMapper.insert(user);

        // 为新用户创建默认「自选股」分组
        groupService.createGroup(user.getId(), "自选股", "默认自选股分组");

        log.info("User registered: {}", user.getUsername());

        // 4. 返回 JWT
        String token = jwtUtil.generateToken(user.getId(), user.getUsername());
        long expireAt = System.currentTimeMillis() / 1000 + jwtUtil.getExpirationMs() / 1000;
        return new LoginResponse(token, expireAt);
    }

    @Override
    public LoginResponse login(LoginRequest req) {
        User user = userMapper.selectOne(
                new LambdaQueryWrapper<User>().eq(User::getUsername, req.getUsername()));
        if (user == null || user.getStatus() == 0) {
            throw new BusinessException(ErrorCode.USERNAME_PASSWORD_ERR, "用户名或密码错误");
        }

        if (!user.getPasswordHash().equals(hashPassword(req.getPassword()))) {
            throw new BusinessException(ErrorCode.USERNAME_PASSWORD_ERR, "用户名或密码错误");
        }

        log.info("User logged in: {}", user.getUsername());

        String token = jwtUtil.generateToken(user.getId(), user.getUsername());
        long expireAt = System.currentTimeMillis() / 1000 + jwtUtil.getExpirationMs() / 1000;
        return new LoginResponse(token, expireAt);
    }

    private String hashPassword(String raw) {
        // 简化 BCrypt：使用两次 MD5 + salt（生产环境应替换为 Spring Security BCryptPasswordEncoder）
        String salt = "sirs";
        String first = DigestUtils.md5DigestAsHex((raw + salt).getBytes(StandardCharsets.UTF_8));
        return DigestUtils.md5DigestAsHex((first + salt).getBytes(StandardCharsets.UTF_8));
    }
}
