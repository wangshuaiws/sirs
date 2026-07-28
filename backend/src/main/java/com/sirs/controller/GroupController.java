package com.sirs.controller;

import com.sirs.dto.*;
import com.sirs.entity.StockGroup;
import com.sirs.service.GroupService;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/groups")
public class GroupController {

    private final GroupService groupService;

    public GroupController(GroupService groupService) {
        this.groupService = groupService;
    }

    private Long getUserId(HttpServletRequest request) {
        return (Long) request.getAttribute("userId");
    }

    @GetMapping
    public Result<List<StockGroup>> list(HttpServletRequest request) {
        return Result.success(groupService.listGroups(getUserId(request)));
    }

    @PostMapping
    public Result<StockGroup> create(@Valid @RequestBody GroupRequest req,
                                      HttpServletRequest request) {
        return Result.success(groupService.createGroup(
                getUserId(request), req.getName(), req.getDescription()));
    }

    @PutMapping("/{id}")
    public Result<StockGroup> update(@PathVariable Long id,
                                      @Valid @RequestBody GroupRequest req,
                                      HttpServletRequest request) {
        return Result.success(groupService.updateGroup(
                getUserId(request), id, req.getName(), req.getDescription()));
    }

    @DeleteMapping("/{id}")
    public Result<Void> delete(@PathVariable Long id, HttpServletRequest request) {
        groupService.deleteGroup(getUserId(request), id);
        return Result.success();
    }

    @GetMapping("/{id}/stocks")
    public Result<List<Map<String, Object>>> getStocks(@PathVariable Long id,
                                                        HttpServletRequest request) {
        return Result.success(groupService.getGroupStocks(getUserId(request), id));
    }

    @PostMapping("/{id}/stocks")
    public Result<Void> addStock(@PathVariable Long id,
                                  @RequestBody AddStockRequest req,
                                  HttpServletRequest request) {
        groupService.addStockToGroup(getUserId(request), id, req.getCode());
        return Result.success();
    }

    @DeleteMapping("/{id}/stocks/{code}")
    public Result<Void> removeStock(@PathVariable Long id,
                                     @PathVariable String code,
                                     HttpServletRequest request) {
        groupService.removeStockFromGroup(getUserId(request), id, code);
        return Result.success();
    }

    @GetMapping("/watchlist/{code}")
    public Result<Map<String, Object>> checkWatchlist(@PathVariable String code,
                                                       HttpServletRequest request) {
        Long userId = getUserId(request);
        boolean inWatchlist = groupService.isInWatchlist(userId, code);
        return Result.success(Map.of("inWatchlist", inWatchlist));
    }
}
