package com.sirs.service;

import com.sirs.entity.StockGroup;
import java.util.List;
import java.util.Map;

public interface GroupService {
    List<StockGroup> listGroups(Long userId);
    StockGroup createGroup(Long userId, String name, String description);
    StockGroup updateGroup(Long userId, Long groupId, String name, String description);
    void deleteGroup(Long userId, Long groupId);
    List<Map<String, Object>> getGroupStocks(Long userId, Long groupId);
    void addStockToGroup(Long userId, Long groupId, String stockCode);
    void removeStockFromGroup(Long userId, Long groupId, String stockCode);
    boolean isInWatchlist(Long userId, String stockCode);
}
