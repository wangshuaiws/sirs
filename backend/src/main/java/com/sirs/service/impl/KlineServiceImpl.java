package com.sirs.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sirs.entity.XdxrEvent;
import com.sirs.mapper.XdxrEventMapper;
import com.sirs.service.KlineService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.LocalDate;
import java.util.*;

@Service
public class KlineServiceImpl implements KlineService {

    private static final Logger log = LoggerFactory.getLogger(KlineServiceImpl.class);
    private static final String TD_REST = "http://localhost:6041/rest/sql";
    private static final String AUTH = "Basic " +
            Base64.getEncoder().encodeToString("root:taosdata".getBytes(StandardCharsets.UTF_8));

    private final HttpClient httpClient = HttpClient.newHttpClient();
    private final ObjectMapper objectMapper = new ObjectMapper();
    private final XdxrEventMapper xdxrEventMapper;

    public KlineServiceImpl(XdxrEventMapper xdxrEventMapper) {
        this.xdxrEventMapper = xdxrEventMapper;
    }

    @Override
    public List<Map<String, Object>> getKline(String code, String period, String from, String to, boolean adjusted) {
        if (!adjusted) {
            // 不复权：直接走 TDengine INTERVAL 聚合（原逻辑）
            String sql = buildKlineSql(code, period, from, to);
            return executeAndParse(sql);
        }

        // 前复权模式：从最早数据开始取日线（需要全量历史才能正确累积复权因子）
        // 只用 45 天扩展不够，早期除权事件的 close_before 会算错导致因子崩溃
        String safeFrom = "2000-01-01";
        String safeTo = (to != null) ? to : "2099-12-31";

        // 1. 从 TDengine 取日线原始数据
        List<Map<String, Object>> dailyData = fetchDailyBars(code, safeFrom, safeTo);
        if (dailyData.isEmpty()) return dailyData;

        // 2. 从 PG 查复权事件
        List<XdxrEvent> events = xdxrEventMapper.selectList(
                new LambdaQueryWrapper<XdxrEvent>()
                        .eq(XdxrEvent::getCode, code)
                        .orderByDesc(XdxrEvent::getExDate)
        );

        // 3. 应用前复权
        List<Map<String, Object>> adjustedData = applyForwardAdjustment(dailyData, events);

        // 4. 裁切回原始日期范围
        List<Map<String, Object>> trimmed = trimToRange(adjustedData, from, to);

        // 5. 如果是周K/月K，在 Java 中聚合
        if ("weekly".equals(period) || "monthly".equals(period)) {
            return aggregatePeriod(trimmed, period);
        }
        return trimmed;
    }

    // ── TDengine 查询 ────────────────────────────────────────────────

    private String buildKlineSql(String code, String period, String from, String to) {
        String tbl = "sirs.k_1d_" + code;
        String where = "WHERE ts >= '" + (from != null ? from : "2000-01-01") +
                       "' AND ts <= '" + (to != null ? to : "2099-12-31") + "'";

        return switch (period) {
            case "weekly" -> "SELECT _wstart AS ts, FIRST(open) AS open, MAX(high) AS high, " +
                    "MIN(low) AS low, LAST(close) AS close, SUM(volume) AS volume, " +
                    "SUM(amount) AS amount, AVG(turnover) AS turnover " +
                    "FROM " + tbl + " " + where + " INTERVAL(1w)";

            case "monthly" -> "SELECT _wstart AS ts, FIRST(open) AS open, MAX(high) AS high, " +
                    "MIN(low) AS low, LAST(close) AS close, SUM(volume) AS volume, " +
                    "SUM(amount) AS amount, AVG(turnover) AS turnover " +
                    "FROM " + tbl + " " + where + " INTERVAL(1mo)";

            default -> "SELECT ts, open, high, low, close, volume, amount, turnover " +
                       "FROM " + tbl + " " + where + " ORDER BY ts";
        };
    }

    private List<Map<String, Object>> fetchDailyBars(String code, String from, String to) {
        String safeFrom = (from != null) ? from : "2000-01-01";
        String safeTo = (to != null) ? to : "2099-12-31";
        String sql = "SELECT ts, open, high, low, close, volume, amount, turnover " +
                     "FROM sirs.k_1d_" + code + " " +
                     "WHERE ts >= '" + safeFrom + "' AND ts <= '" + safeTo + "' ORDER BY ts";
        return executeAndParse(sql);
    }

    private List<Map<String, Object>> executeAndParse(String sql) {
        log.debug("TDengine query: {}", sql);
        try {
            HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create(TD_REST))
                    .header("Authorization", AUTH)
                    .POST(HttpRequest.BodyPublishers.ofString(sql, StandardCharsets.UTF_8))
                    .timeout(Duration.ofSeconds(30))
                    .build();

            HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString());

            if (response.statusCode() != 200) {
                log.error("TDengine error: {} {}", response.statusCode(), response.body());
                return List.of();
            }

            @SuppressWarnings("unchecked")
            Map<String, Object> result = objectMapper.readValue(response.body(), Map.class);
            if (!"0".equals(String.valueOf(result.get("code")))) {
                log.error("TDengine SQL error: {}", result);
                return List.of();
            }

            return parseResult(result);

        } catch (Exception e) {
            log.error("Query TDengine failed: {}", e.getMessage());
            return List.of();
        }
    }

    @SuppressWarnings("unchecked")
    private List<Map<String, Object>> parseResult(Map<String, Object> result) {
        List<Map<String, Object>> list = new ArrayList<>();

        List<String> colNames = new ArrayList<>();
        Object colMeta = result.get("column_meta");
        if (colMeta instanceof List<?> cols) {
            for (Object c : cols) {
                if (c instanceof List<?> pair && pair.size() >= 1) {
                    colNames.add(String.valueOf(pair.get(0)));
                }
            }
        }

        Object data = result.get("data");
        if (data instanceof List<?> rows) {
            for (Object row : rows) {
                if (row instanceof List<?> values) {
                    Map<String, Object> item = new LinkedHashMap<>();
                    for (int i = 0; i < Math.min(colNames.size(), values.size()); i++) {
                        Object val = values.get(i);
                        if (i == 0 && "ts".equals(colNames.get(i)) && val instanceof String s) {
                            val = s.length() > 10 ? s.substring(0, 10) : s;
                        }
                        item.put(colNames.get(i), val);
                    }
                    list.add(item);
                }
            }
        }
        return list;
    }

    // ── 前复权算法 ───────────────────────────────────────────────────

    /**
     * 对日线 OHLC 数据应用前复权。
     * 算法移植自 Python apply_forward_adjustment()。
     */
    private List<Map<String, Object>> applyForwardAdjustment(
            List<Map<String, Object>> bars, List<XdxrEvent> events) {

        if (bars == null || bars.isEmpty() || events == null || events.isEmpty()) {
            return bars;
        }

        // 深拷贝一份原始 close 用于计算现金分红因子（必须用原始价，否则累积因子会递减到负数）
        Map<String, Double> rawClose = new LinkedHashMap<>();
        for (Map<String, Object> bar : bars) {
            String ts = (String) bar.get("ts");
            if (ts != null) {
                rawClose.put(ts, toDouble(bar.get("close")));
            }
        }

        // events 已按 ex_date DESC 排序
        for (XdxrEvent event : events) {
            LocalDate exDate = event.getExDate();
            int cat = event.getCategory() != null ? event.getCategory() : 0;
            double fen = event.getFenhong() != null ? event.getFenhong() : 0.0;
            double song = event.getSongzhuangu() != null ? event.getSongzhuangu() : 0.0;
            double pei = event.getPeigu() != null ? event.getPeigu() : 0.0;
            double peijia = event.getPeigujia() != null ? event.getPeigujia() : 0.0;

            if (fen <= 0 && song <= 0 && pei <= 0) continue;

            // 找除权日前最后一个 bar（用当前调整后的 bars，因 mask 需要正确索引）
            int lastBeforeIdx = -1;
            String lastBeforeTs = null;
            for (int i = bars.size() - 1; i >= 0; i--) {
                LocalDate barDate = toDate(bars.get(i).get("ts"));
                if (barDate != null && barDate.isBefore(exDate)) {
                    lastBeforeIdx = i;
                    lastBeforeTs = (String) bars.get(i).get("ts");
                    break;
                }
            }
            if (lastBeforeIdx < 0) continue;

            // 计算复权因子（category=1 可同时包含现金分红+送转股+配股）
            double factor = 1.0;

            // 现金分红：fenhong 是"每10股派息"，需除以10得到每股；用原始收盘价计算因子
            if (cat == 1 && fen > 0) {
                double origClose = rawClose.getOrDefault(lastBeforeTs, 0.0);
                double fenPerShare = fen / 10.0;  // fenhong = 每10股派息金额
                if (origClose > 0) {
                    factor = (origClose - fenPerShare) / origClose;
                }
            }
            // 送转股（category 1-14 都可能包含）
            if (song > 0) {
                factor *= 1.0 / (1.0 + song / 10.0);
            }
            // 配股（category 1-14 都可能包含，用原始收盘价）
            if (pei > 0 && peijia > 0) {
                double origClose = rawClose.getOrDefault(lastBeforeTs, 0.0);
                if (origClose > 0) {
                    double peiFactor = (origClose + peijia * pei / 10.0)
                                     / (origClose * (1.0 + pei / 10.0));
                    factor *= peiFactor;
                }
            }

            // 应用到除权日之前的所有 bar
            if (Math.abs(factor - 1.0) > 0.0001) {
                for (int i = 0; i <= lastBeforeIdx; i++) {
                    Map<String, Object> bar = bars.get(i);
                    bar.put("open",  toDouble(bar.get("open"))  * factor);
                    bar.put("high",  toDouble(bar.get("high"))  * factor);
                    bar.put("low",   toDouble(bar.get("low"))   * factor);
                    bar.put("close", toDouble(bar.get("close")) * factor);
                }
            }
        }

        return bars;
    }

    // ── 日期范围裁切 ────────────────────────────────────────────────

    private List<Map<String, Object>> trimToRange(
            List<Map<String, Object>> data, String from, String to) {
        if (from == null && to == null) return data;

        LocalDate fromDate = from != null ? LocalDate.parse(from) : null;
        LocalDate toDate = to != null ? LocalDate.parse(to) : null;

        List<Map<String, Object>> result = new ArrayList<>();
        for (Map<String, Object> bar : data) {
            LocalDate barDate = toDate(bar.get("ts"));
            if (barDate == null) continue;
            if (fromDate != null && barDate.isBefore(fromDate)) continue;
            if (toDate != null && barDate.isAfter(toDate)) continue;
            result.add(bar);
        }
        return result;
    }

    // ── 周K/月K 聚合（复权后）───────────────────────────────────────

    private List<Map<String, Object>> aggregatePeriod(
            List<Map<String, Object>> dailyData, String period) {

        if (dailyData == null || dailyData.isEmpty()) return dailyData;

        boolean isWeekly = "weekly".equals(period);
        Map<String, List<Map<String, Object>>> groups = new LinkedHashMap<>();

        for (Map<String, Object> bar : dailyData) {
            LocalDate date = toDate(bar.get("ts"));
            if (date == null) continue;

            String key;
            if (isWeekly) {
                // ISO week: year-Www
                int weekOfYear = date.get(java.time.temporal.IsoFields.WEEK_OF_WEEK_BASED_YEAR);
                key = date.getYear() + "-W" + String.format("%02d", weekOfYear);
            } else {
                key = date.getYear() + "-" + String.format("%02d", date.getMonthValue());
            }
            groups.computeIfAbsent(key, k -> new ArrayList<>()).add(bar);
        }

        List<Map<String, Object>> result = new ArrayList<>();
        for (List<Map<String, Object>> group : groups.values()) {
            Map<String, Object> agg = new LinkedHashMap<>();

            // ts: 周期内第一个交易日
            agg.put("ts", group.get(0).get("ts"));

            // FIRST(open)
            agg.put("open", group.get(0).get("open"));

            // MAX(high)
            double maxHigh = group.stream()
                    .mapToDouble(m -> toDouble(m.get("high")))
                    .max().orElse(0);
            agg.put("high", maxHigh);

            // MIN(low)
            double minLow = group.stream()
                    .mapToDouble(m -> toDouble(m.get("low")))
                    .min().orElse(0);
            agg.put("low", minLow);

            // LAST(close)
            agg.put("close", group.get(group.size() - 1).get("close"));

            // SUM(volume)
            long sumVol = group.stream()
                    .mapToLong(m -> (long) toDouble(m.get("volume")))
                    .sum();
            agg.put("volume", sumVol);

            // SUM(amount)
            double sumAmt = group.stream()
                    .mapToDouble(m -> toDouble(m.get("amount")))
                    .sum();
            agg.put("amount", sumAmt);

            // AVG(turnover)
            double avgTor = group.stream()
                    .mapToDouble(m -> toDouble(m.get("turnover")))
                    .average().orElse(0);
            agg.put("turnover", avgTor);

            result.add(agg);
        }
        return result;
    }

    // ── 工具方法 ────────────────────────────────────────────────────

    private double toDouble(Object value) {
        if (value == null) return 0.0;
        if (value instanceof Number n) return n.doubleValue();
        try {
            return Double.parseDouble(value.toString());
        } catch (NumberFormatException e) {
            return 0.0;
        }
    }

    private LocalDate toDate(Object ts) {
        if (ts == null) return null;
        String s = ts.toString();
        if (s.length() >= 10) s = s.substring(0, 10);
        try {
            return LocalDate.parse(s);
        } catch (Exception e) {
            return null;
        }
    }

    private String extendDate(String dateStr, int offsetDays) {
        if (dateStr == null) return null;
        try {
            LocalDate date = LocalDate.parse(dateStr);
            return date.plusDays(offsetDays).toString();
        } catch (Exception e) {
            return dateStr;
        }
    }
}
