package com.sirs.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.sirs.dto.NotificationQuery;
import com.sirs.dto.PageResult;
import com.sirs.entity.Notification;
import com.sirs.mapper.NotificationMapper;
import com.sirs.service.NotificationService;
import org.springframework.stereotype.Service;

import java.util.*;

@Service
public class NotificationServiceImpl implements NotificationService {

    private final NotificationMapper notificationMapper;

    public NotificationServiceImpl(NotificationMapper notificationMapper) {
        this.notificationMapper = notificationMapper;
    }

    @Override
    public PageResult<Notification> list(Long userId, NotificationQuery query) {
        LambdaQueryWrapper<Notification> wrapper = new LambdaQueryWrapper<Notification>()
                .eq(Notification::getUserId, userId);

        if (query.getType() != null && !query.getType().isEmpty()) {
            wrapper.eq(Notification::getType, query.getType());
        }
        if (query.getKeyword() != null && !query.getKeyword().isEmpty()) {
            wrapper.and(w ->
                w.like(Notification::getStockCode, query.getKeyword())
                 .or()
                 .like(Notification::getStockName, query.getKeyword())
            );
        }
        if (query.getDateFrom() != null && !query.getDateFrom().isEmpty()) {
            wrapper.ge(Notification::getCreatedAt, query.getDateFrom() + " 00:00:00");
        }
        if (query.getDateTo() != null && !query.getDateTo().isEmpty()) {
            wrapper.le(Notification::getCreatedAt, query.getDateTo() + " 23:59:59");
        }

        wrapper.orderByDesc(Notification::getCreatedAt);

        Page<Notification> page = new Page<>(query.getPage(), query.getSize());
        notificationMapper.selectPage(page, wrapper);

        return new PageResult<>(
                page.getRecords(),
                page.getTotal(),
                (int) page.getCurrent(),
                (int) page.getSize()
        );
    }

    @Override
    public Map<String, Long> stats(Long userId) {
        List<Map<String, Object>> totalRows = notificationMapper.countByType(userId);
        List<Map<String, Object>> unreadRows = notificationMapper.countUnreadByType(userId);

        Map<String, Long> result = new LinkedHashMap<>();
        result.put("total", 0L);
        result.put("unreadTotal", 0L);
        result.put("goldenCross", 0L);
        result.put("goldenCrossUnread", 0L);
        result.put("whiteLineBuy", 0L);
        result.put("whiteLineBuyUnread", 0L);
        result.put("yellowLineBuy", 0L);
        result.put("yellowLineBuyUnread", 0L);
        result.put("clearPosition", 0L);
        result.put("clearPositionUnread", 0L);
        result.put("reAttention", 0L);
        result.put("reAttentionUnread", 0L);

        // 总数
        long total = 0;
        for (Map<String, Object> row : totalRows) {
            String type = (String) row.get("type");
            long count = ((Number) row.get("count")).longValue();
            total += count;
            switch (type) {
                case "GOLDEN_CROSS"    -> result.put("goldenCross", count);
                case "WHITE_LINE_BUY"  -> result.put("whiteLineBuy", count);
                case "YELLOW_LINE_BUY" -> result.put("yellowLineBuy", count);
                case "CLEAR_POSITION"  -> result.put("clearPosition", count);
                case "RE_ATTENTION"    -> result.put("reAttention", count);
            }
        }
        result.put("total", total);

        // 未读数
        long unreadTotal = 0;
        for (Map<String, Object> row : unreadRows) {
            String type = (String) row.get("type");
            long count = ((Number) row.get("count")).longValue();
            unreadTotal += count;
            switch (type) {
                case "GOLDEN_CROSS"    -> result.put("goldenCrossUnread", count);
                case "WHITE_LINE_BUY"  -> result.put("whiteLineBuyUnread", count);
                case "YELLOW_LINE_BUY" -> result.put("yellowLineBuyUnread", count);
                case "CLEAR_POSITION"  -> result.put("clearPositionUnread", count);
                case "RE_ATTENTION"    -> result.put("reAttentionUnread", count);
            }
        }
        result.put("unreadTotal", unreadTotal);
        return result;
    }

    @Override
    public void markRead(Long userId, Long id) {
        Notification notification = notificationMapper.selectById(id);
        if (notification == null || !notification.getUserId().equals(userId)) {
            throw new BusinessException(5001, "通知不存在");
        }
        notification.setIsRead(true);
        notificationMapper.updateById(notification);
    }

    @Override
    public void markAllRead(Long userId) {
        List<Notification> unread = notificationMapper.selectList(
                new LambdaQueryWrapper<Notification>()
                        .eq(Notification::getUserId, userId)
                        .eq(Notification::getIsRead, false)
        );
        for (Notification n : unread) {
            n.setIsRead(true);
            notificationMapper.updateById(n);
        }
    }
}
