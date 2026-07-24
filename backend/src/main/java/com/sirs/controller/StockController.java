package com.sirs.controller;

import com.sirs.dto.Result;
import com.sirs.entity.Stock;
import com.sirs.service.KlineService;
import com.sirs.service.StockService;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api")
public class StockController {

    private final StockService stockService;
    private final KlineService klineService;

    public StockController(StockService stockService, KlineService klineService) {
        this.stockService = stockService;
        this.klineService = klineService;
    }

    @GetMapping("/stocks/search")
    public Result<List<Stock>> search(@RequestParam(name = "keyword", required = false) String keyword) {
        return Result.success(stockService.search(keyword));
    }

    @GetMapping("/stocks/{code}")
    public Result<Stock> getStock(@PathVariable String code) {
        return Result.success(stockService.getByCode(code));
    }

    @GetMapping("/kline/{code}")
    public Result<List<Map<String, Object>>> kline(
            @PathVariable String code,
            @RequestParam(defaultValue = "daily") String period,
            @RequestParam(required = false) String from,
            @RequestParam(required = false) String to,
            @RequestParam(defaultValue = "true") boolean adjusted) {
        return Result.success(klineService.getKline(code, period, from, to, adjusted));
    }
}
