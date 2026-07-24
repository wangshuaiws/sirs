package com.sirs.service;

import com.sirs.dto.*;

public interface AuthService {
    CaptchaResponse generateCaptcha();
    LoginResponse register(RegisterRequest req);
    LoginResponse login(LoginRequest req);
}
