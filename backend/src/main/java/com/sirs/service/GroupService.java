package com.sirs.service;

import com.sirs.dto.GroupStockVO;
import com.sirs.dto.PageResult;
import com.sirs.entity.StockGroup;
import java.util.List;

public interface GroupService {
    List<StockGroup> listGroups(Long userId);
    StockGroup createGroup(Long userId, String name, String description);
    StockGroup updateGroup(Long userId, Long groupId, String name, String description);
    void deleteGroup(Long userId, Long groupId);
    PageResult<GroupStockVO> getGroupStocks(Long userId, Long groupId, int page, int size);
    void addStockToGroup(Long userId, Long groupId, String stockCode);
    void removeStockFromGroup(Long userId, Long groupId, String stockCode);
    boolean isInWatchlist(Long userId, String stockCode);
}
