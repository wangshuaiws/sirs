package com.sirs.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.sirs.entity.GroupStock;
import com.sirs.entity.Stock;
import com.sirs.entity.StockGroup;
import com.sirs.mapper.GroupStockMapper;
import com.sirs.mapper.StockGroupMapper;
import com.sirs.mapper.StockMapper;
import com.sirs.service.GroupService;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.*;

@Service
public class GroupServiceImpl implements GroupService {

    private final StockGroupMapper groupMapper;
    private final GroupStockMapper groupStockMapper;
    private final StockMapper stockMapper;

    public GroupServiceImpl(StockGroupMapper groupMapper,
                            GroupStockMapper groupStockMapper,
                            StockMapper stockMapper) {
        this.groupMapper = groupMapper;
        this.groupStockMapper = groupStockMapper;
        this.stockMapper = stockMapper;
    }

    @Override
    public List<StockGroup> listGroups(Long userId) {
        return groupMapper.selectList(
                new LambdaQueryWrapper<StockGroup>()
                        .eq(StockGroup::getUserId, userId)
                        .orderByAsc(StockGroup::getSortOrder));
    }

    @Override
    public StockGroup createGroup(Long userId, String name, String description) {
        // 检查同名
        Long count = groupMapper.selectCount(
                new LambdaQueryWrapper<StockGroup>()
                        .eq(StockGroup::getUserId, userId)
                        .eq(StockGroup::getName, name));
        if (count > 0) {
            throw new BusinessException(4001, "分组名已存在");
        }

        StockGroup group = new StockGroup();
        group.setUserId(userId);
        group.setName(name);
        group.setDescription(description);
        group.setSortOrder(0);
        groupMapper.insert(group);
        return group;
    }

    @Override
    public StockGroup updateGroup(Long userId, Long groupId, String name, String description) {
        StockGroup group = getAndVerifyOwner(userId, groupId);

        if (name != null && !name.isBlank()) {
            group.setName(name);
        }
        if (description != null) {
            group.setDescription(description);
        }
        groupMapper.updateById(group);
        return group;
    }

    @Override
    @Transactional
    public void deleteGroup(Long userId, Long groupId) {
        StockGroup group = getAndVerifyOwner(userId, groupId);
        if ("自选股".equals(group.getName())) {
            throw new BusinessException(4004, "自选股分组不可删除");
        }
        // 级联删除关联
        groupStockMapper.delete(
                new LambdaQueryWrapper<GroupStock>().eq(GroupStock::getGroupId, groupId));
        groupMapper.deleteById(groupId);
    }

    @Override
    public List<Map<String, Object>> getGroupStocks(Long userId, Long groupId) {
        getAndVerifyOwner(userId, groupId);

        List<GroupStock> relations = groupStockMapper.selectList(
                new LambdaQueryWrapper<GroupStock>().eq(GroupStock::getGroupId, groupId));

        if (relations.isEmpty()) {
            return List.of();
        }

        List<String> codes = relations.stream().map(GroupStock::getStockCode).toList();
        List<Stock> stocks = stockMapper.selectList(
                new LambdaQueryWrapper<Stock>().in(Stock::getCode, codes));

        Map<String, Stock> stockMap = new HashMap<>();
        for (Stock s : stocks) {
            stockMap.put(s.getCode(), s);
        }

        List<Map<String, Object>> result = new ArrayList<>();
        for (GroupStock gs : relations) {
            Stock s = stockMap.get(gs.getStockCode());
            if (s != null) {
                Map<String, Object> item = new LinkedHashMap<>();
                item.put("code", s.getCode());
                item.put("name", s.getName());
                item.put("exchange", s.getExchange());
                item.put("industry", s.getIndustry());
                item.put("addedAt", gs.getAddedAt());
                result.add(item);
            }
        }
        return result;
    }

    @Override
    public void addStockToGroup(Long userId, Long groupId, String stockCode) {
        StockGroup group = getAndVerifyOwner(userId, groupId);

        // 检查股票是否存在
        Stock stock = stockMapper.selectOne(
                new LambdaQueryWrapper<Stock>().eq(Stock::getCode, stockCode));
        if (stock == null) {
            throw new BusinessException(3001, "股票代码不存在");
        }

        // 检查是否已在分组中
        Long count = groupStockMapper.selectCount(
                new LambdaQueryWrapper<GroupStock>()
                        .eq(GroupStock::getGroupId, groupId)
                        .eq(GroupStock::getStockCode, stockCode));
        if (count > 0) {
            throw new BusinessException(4003, "股票已在分组中");
        }

        GroupStock gs = new GroupStock();
        gs.setGroupId(groupId);
        gs.setStockCode(stockCode);
        groupStockMapper.insert(gs);

        // 添加到其他分组时，同步到自选股默认分组
        if (!"自选股".equals(group.getName())) {
            syncToWatchlist(userId, stockCode);
        }
    }

    /**
     * 将股票同步到用户的「自选股」默认分组（不存在则创建）
     */
    private void syncToWatchlist(Long userId, String stockCode) {
        // 查找或创建自选股分组
        StockGroup watchlist = groupMapper.selectOne(
                new LambdaQueryWrapper<StockGroup>()
                        .eq(StockGroup::getUserId, userId)
                        .eq(StockGroup::getName, "自选股"));
        if (watchlist == null) {
            watchlist = new StockGroup();
            watchlist.setUserId(userId);
            watchlist.setName("自选股");
            watchlist.setSortOrder(0);
            groupMapper.insert(watchlist);
        }

        // 如果自选股中已存在，跳过
        Long exists = groupStockMapper.selectCount(
                new LambdaQueryWrapper<GroupStock>()
                        .eq(GroupStock::getGroupId, watchlist.getId())
                        .eq(GroupStock::getStockCode, stockCode));
        if (exists > 0) {
            return;
        }

        GroupStock gs = new GroupStock();
        gs.setGroupId(watchlist.getId());
        gs.setStockCode(stockCode);
        groupStockMapper.insert(gs);
    }

    @Override
    public void removeStockFromGroup(Long userId, Long groupId, String stockCode) {
        getAndVerifyOwner(userId, groupId);

        groupStockMapper.delete(
                new LambdaQueryWrapper<GroupStock>()
                        .eq(GroupStock::getGroupId, groupId)
                        .eq(GroupStock::getStockCode, stockCode));
    }

    private StockGroup getAndVerifyOwner(Long userId, Long groupId) {
        StockGroup group = groupMapper.selectById(groupId);
        if (group == null) {
            throw new BusinessException(4002, "分组不存在");
        }
        if (!group.getUserId().equals(userId)) {
            throw new BusinessException(1004, "无操作权限");
        }
        return group;
    }
}
