package com.sirs.dto;

public final class ErrorCode {
    private ErrorCode() {}

    // 系统 1xxx
    public static final int PARAM_INVALID     = 1001;
    public static final int CAPTCHA_ERROR     = 1002;
    public static final int NOT_AUTHENTICATED = 1003;
    public static final int NO_PERMISSION     = 1004;
    public static final int RATE_LIMITED      = 1005;
    public static final int NOT_FOUND         = 1006;
    public static final int INTERNAL_ERROR    = 1007;

    // 用户 2xxx
    public static final int USERNAME_EXISTS       = 2001;
    public static final int USERNAME_PASSWORD_ERR = 2002;

    // 股票 3xxx
    public static final int STOCK_NOT_FOUND = 3001;
    public static final int NO_KLINE_DATA   = 3002;

    // 分组 4xxx
    public static final int GROUP_NAME_EXISTS  = 4001;
    public static final int GROUP_NOT_FOUND    = 4002;
    public static final int STOCK_ALREADY_IN   = 4003;

    // 通知 5xxx
    public static final int NOTIFICATION_NOT_FOUND = 5001;
}
