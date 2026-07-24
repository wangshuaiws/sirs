package com.sirs.controller;

import com.sirs.dto.NotificationQuery;
import com.sirs.dto.PageResult;
import com.sirs.dto.Result;
import com.sirs.entity.Notification;
import com.sirs.service.NotificationService;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

@RestController
@RequestMapping("/api/notifications")
public class NotificationController {

    private final NotificationService notificationService;

    public NotificationController(NotificationService notificationService) {
        this.notificationService = notificationService;
    }

    private Long getUserId(HttpServletRequest request) {
        return (Long) request.getAttribute("userId");
    }

    /** 分页查询通知列表，支持按类型/关键词/日期范围筛选 */
    @GetMapping
    public Result<PageResult<Notification>> list(HttpServletRequest request,
                                                  NotificationQuery query) {
        return Result.success(notificationService.list(getUserId(request), query));
    }

    /** 各类型通知数量统计 */
    @GetMapping("/stats")
    public Result<Map<String, Long>> stats(HttpServletRequest request) {
        return Result.success(notificationService.stats(getUserId(request)));
    }

    /** 标记单条已读 */
    @PutMapping("/{id}/read")
    public Result<Void> markRead(@PathVariable Long id, HttpServletRequest request) {
        notificationService.markRead(getUserId(request), id);
        return Result.success();
    }

    /** 全部标为已读 */
    @PutMapping("/read-all")
    public Result<Void> markAllRead(HttpServletRequest request) {
        notificationService.markAllRead(getUserId(request));
        return Result.success();
    }
}
