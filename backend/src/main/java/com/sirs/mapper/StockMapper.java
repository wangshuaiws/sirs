package com.sirs.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.sirs.entity.Stock;
import org.apache.ibatis.annotations.Mapper;

@Mapper
public interface StockMapper extends BaseMapper<Stock> {
}
