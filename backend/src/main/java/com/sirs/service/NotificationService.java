package com.sirs.service;

import com.sirs.dto.NotificationQuery;
import com.sirs.dto.PageResult;
import com.sirs.entity.Notification;

import java.util.Map;

public interface NotificationService {
    PageResult<Notification> list(Long userId, NotificationQuery query);
    Map<String, Long> stats(Long userId);
    void markRead(Long userId, Long id);
    void markAllRead(Long userId);
}
