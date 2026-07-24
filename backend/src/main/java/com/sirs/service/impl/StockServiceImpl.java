package com.sirs.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.sirs.entity.Stock;
import com.sirs.mapper.StockMapper;
import com.sirs.service.StockService;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
public class StockServiceImpl implements StockService {

    private final StockMapper stockMapper;

    public StockServiceImpl(StockMapper stockMapper) {
        this.stockMapper = stockMapper;
    }

    @Override
    public List<Stock> search(String keyword) {
        if (keyword == null || keyword.isBlank()) {
            return List.of();
        }
        return stockMapper.selectList(
                new LambdaQueryWrapper<Stock>()
                        .and(w -> w.like(Stock::getCode, keyword).or().like(Stock::getName, keyword))
                        .eq(Stock::getIsActive, true)
                        .last("LIMIT 6")
        );
    }

    @Override
    public Stock getByCode(String code) {
        Stock stock = stockMapper.selectOne(
                new LambdaQueryWrapper<Stock>().eq(Stock::getCode, code));
        if (stock == null) {
            throw new BusinessException(3001, "股票代码不存在");
        }
        return stock;
    }
}
