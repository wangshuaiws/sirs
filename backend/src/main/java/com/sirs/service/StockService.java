package com.sirs.service;

import com.sirs.entity.Stock;
import java.util.List;

public interface StockService {
    List<Stock> search(String keyword);
    Stock getByCode(String code);
}
