package com.sirs.service.impl;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sirs.service.KlineService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.util.*;

@Service
public class KlineServiceImpl implements KlineService {

    private static final Logger log = LoggerFactory.getLogger(KlineServiceImpl.class);
    private static final String TD_REST = "http://localhost:6041/rest/sql";
    private static final String AUTH = "Basic " +
            Base64.getEncoder().encodeToString("root:taosdata".getBytes(StandardCharsets.UTF_8));
    private static final String CACHE_PREFIX = "kline:";

    private final HttpClient httpClient = HttpClient.newHttpClient();
    private final ObjectMapper objectMapper = new ObjectMapper();
    private final StringRedisTemplate redis;

    public KlineServiceImpl(StringRedisTemplate redis) {
        this.redis = redis;
    }

    @Override
    public List<Map<String, Object>> getKline(String code, String period, String from, String to, boolean adjusted) {
        // 周线/月线：全历史聚合 + 全量算指标 + 切片
        // 长周期指标(MA120/MA233/ZXDKX)需要远超请求窗口的历史，按窗口现算会整条 null；
        // 改为全量算指标后切片，保证任意请求范围内指标正确，且 loadEarlier 拼接连续无断档。
        if ("weekly".equals(period) || "monthly".equals(period)) {
            String fullKey = CACHE_PREFIX + code + ":" + period + ":" + adjusted + ":full:v4";
            List<Map<String, Object>> full = readCache(fullKey);
            if (full == null) {
                full = adjusted
                        ? computeFullPeriodAdjusted(code, period)
                        : computeFullPeriodRaw(code, period);
                writeCache(fullKey, full);
            }
            return sliceByTs(full, from, to);
        }

        // 日线：按 [from,to] 读预计算表（前复权）或原始表（不复权），per-[from,to] 缓存
        String cacheKey = CACHE_PREFIX + code + ":" + period + ":" + from + ":" + to + ":" + adjusted + ":v3";
        List<Map<String, Object>> cached = readCache(cacheKey);
        if (cached != null) return cached;

        List<Map<String, Object>> data = adjusted
                ? fetchAdjustedBars(code, from, to)
                : executeAndParse(buildKlineSql(code, period, from, to));

        writeCache(cacheKey, data);
        return data;
    }

    /** 前复权周线/月线：全历史前复权日线 → 聚合 → 全量算指标 */
    private List<Map<String, Object>> computeFullPeriodAdjusted(String code, String period) {
        List<Map<String, Object>> daily = fetchAdjustedBars(code, null, null); // null → 2000-01-01 ~ 2099-12-31 全历史
        List<Map<String, Object>> agg = aggregatePeriod(daily, period);
        computeIndicators(agg);
        return agg;
    }

    /** 不复权周线/月线：TDengine INTERVAL 全历史聚合 → 全量算指标 */
    private List<Map<String, Object>> computeFullPeriodRaw(String code, String period) {
        List<Map<String, Object>> agg = executeAndParse(buildKlineSql(code, period, null, null));
        computeIndicators(agg);
        return agg;
    }

    /** 按时间区间切片全量数组（from/to 为 null 时表示该侧不限） */
    private List<Map<String, Object>> sliceByTs(List<Map<String, Object>> full, String from, String to) {
        if (from == null && to == null) return full;
        List<Map<String, Object>> out = new ArrayList<>(full.size());
        for (Map<String, Object> bar : full) {
            String ts = String.valueOf(bar.get("ts"));
            if (from != null && ts.compareTo(from) < 0) continue;
            if (to != null && ts.compareTo(to) > 0) continue;
            out.add(bar);
        }
        return out;
    }

    private List<Map<String, Object>> readCache(String key) {
        try {
            String cached = redis.opsForValue().get(key);
            if (cached != null && !cached.isEmpty()) {
                @SuppressWarnings("unchecked")
                List<Map<String, Object>> result = objectMapper.readValue(cached, List.class);
                return result;
            }
        } catch (Exception e) {
            log.debug("Redis cache read failed: {}", e.getMessage());
        }
        return null;
    }

    private void writeCache(String key, List<Map<String, Object>> data) {
        try {
            String json = objectMapper.writeValueAsString(data);
            redis.opsForValue().set(key, json, Duration.ofSeconds(secondsUntilNext3PM()));
        } catch (Exception e) {
            log.debug("Redis cache write failed: {}", e.getMessage());
        }
    }

    /** 计算距离下一个 15:00 的秒数 */
    private long secondsUntilNext3PM() {
        LocalDateTime now = LocalDateTime.now();
        LocalDateTime next3PM = now.toLocalDate().atTime(LocalTime.of(15, 0));
        if (!now.isBefore(next3PM)) {
            next3PM = next3PM.plusDays(1);
        }
        return Duration.between(now, next3PM).getSeconds();
    }

    // ── TDengine 查询 ────────────────────────────────────────────────

    /** 从 kline_1d_adj 读取前复权日K（已含预计算指标） */
    private List<Map<String, Object>> fetchAdjustedBars(String code, String from, String to) {
        String tbl = "sirs.k_1d_adj_" + code;
        String where = "WHERE ts >= '" + (from != null ? from : "2000-01-01") +
                       "' AND ts <= '" + (to != null ? to : "2099-12-31") + "'";
        String sql = "SELECT ts, open, high, low, close, volume, amount, turnover, " +
                     "ma5, ma10, ma20, ma30, ma60, ma120, ma233, " +
                     "macd_dif, macd_dea, macd_hist, " +
                     "kdj_k, kdj_d, kdj_j, zxdq, zxdkx " +
                     "FROM " + tbl + " " + where + " ORDER BY ts";
        return executeAndParse(sql);
    }

    private String buildKlineSql(String code, String period, String from, String to) {
        String tbl = "sirs.k_1d_" + code;
        String where = "WHERE ts >= '" + (from != null ? from : "2000-01-01") +
                       "' AND ts <= '" + (to != null ? to : "2099-12-31") + "'";

        return switch (period) {
            case "weekly" -> "SELECT LAST(ts) AS ts, FIRST(open) AS open, MAX(high) AS high, " +
                    "MIN(low) AS low, LAST(close) AS close, SUM(volume) AS volume, " +
                    "SUM(amount) AS amount, AVG(turnover) AS turnover " +
                    "FROM " + tbl + " " + where + " INTERVAL(1w)";

            case "monthly" -> "SELECT LAST(ts) AS ts, FIRST(open) AS open, MAX(high) AS high, " +
                    "MIN(low) AS low, LAST(close) AS close, SUM(volume) AS volume, " +
                    "SUM(amount) AS amount, AVG(turnover) AS turnover " +
                    "FROM " + tbl + " " + where + " INTERVAL(1mo)";

            default -> "SELECT ts, open, high, low, close, volume, amount, turnover " +
                       "FROM " + tbl + " " + where + " ORDER BY ts";
        };
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

    // ── 周K/月K 聚合 ───────────────────────────────────────────────

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
                //int weekOfYear = date.get(java.time.temporal.IsoFields.WEEK_OF_WEEK_BASED_YEAR);
                //key = date.getYear() + "-W" + String.format("%02d", weekOfYear);
                int weekOfYear = date.get(java.time.temporal.IsoFields.WEEK_OF_WEEK_BASED_YEAR);
                int weekBasedYear = date.get(java.time.temporal.IsoFields.WEEK_BASED_YEAR);  // 基于周的年
                key = weekBasedYear + "-W" + String.format("%02d", weekOfYear);
            } else {
                key = date.getYear() + "-" + String.format("%02d", date.getMonthValue());
            }
            groups.computeIfAbsent(key, k -> new ArrayList<>()).add(bar);
        }

        List<Map<String, Object>> result = new ArrayList<>();
        for (List<Map<String, Object>> group : groups.values()) {
            Map<String, Object> agg = new LinkedHashMap<>();

            // ts: 周期内最后一个交易日
            agg.put("ts", group.get(group.size() - 1).get("ts"));

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

    // ── 技术指标计算 ─────────────────────────────────────────────────

    /** 为每个 bar 嵌入 MA/MACD/KDJ/ZXDQ/ZXDKX 指标值 */
    private void computeIndicators(List<Map<String, Object>> bars) {
        if (bars == null || bars.isEmpty()) return;
        int len = bars.size();

        // 收盘价数组
        double[] closes = new double[len];
        double[] highs = new double[len];
        double[] lows = new double[len];
        for (int i = 0; i < len; i++) {
            closes[i] = toDouble(bars.get(i).get("close"));
            highs[i] = toDouble(bars.get(i).get("high"));
            lows[i] = toDouble(bars.get(i).get("low"));
        }

        // MA(5,10,20,60,120)
        double[][] mas = new double[5][len];
        int[] maPeriods = {5, 10, 20, 60, 120};
        for (int p = 0; p < maPeriods.length; p++) {
            calcMA(closes, maPeriods[p], mas[p]);
        }

        // MACD(12,26,9)
        double[] dif = new double[len];
        double[] dea = new double[len];
        double[] macdHist = new double[len];
        calcMACD(closes, dif, dea, macdHist);

        // KDJ(9,3,3)
        double[] k = new double[len];
        double[] d = new double[len];
        double[] j = new double[len];
        calcKDJ(highs, lows, closes, k, d, j);

        // ZXDQ / ZXDKX
        double[] zxdq = calcZXDQ(closes);
        double[] zxdkx = calcZXDKX(closes);

        // 嵌入 bar，使用 Double.NaN 表示 null（前端 JSON 序列化后用 null 表示）
        for (int i = 0; i < len; i++) {
            Map<String, Object> bar = bars.get(i);

            if (i >= maPeriods[0] - 1) bar.put("ma5", round2(mas[0][i])); else bar.put("ma5", null);
            if (i >= maPeriods[1] - 1) bar.put("ma10", round2(mas[1][i])); else bar.put("ma10", null);
            if (i >= maPeriods[2] - 1) bar.put("ma20", round2(mas[2][i])); else bar.put("ma20", null);
            if (i >= maPeriods[3] - 1) bar.put("ma60", round2(mas[3][i])); else bar.put("ma60", null);
            if (i >= maPeriods[4] - 1) bar.put("ma120", round2(mas[4][i])); else bar.put("ma120", null);

            bar.put("macd_dif", !Double.isNaN(dif[i]) ? round4(dif[i]) : null);
            bar.put("macd_dea", !Double.isNaN(dea[i]) ? round4(dea[i]) : null);
            bar.put("macd_hist", !Double.isNaN(macdHist[i]) ? round4(macdHist[i]) : null);

            bar.put("kdj_k", !Double.isNaN(k[i]) ? round2(k[i]) : null);
            bar.put("kdj_d", !Double.isNaN(d[i]) ? round2(d[i]) : null);
            bar.put("kdj_j", !Double.isNaN(j[i]) ? round2(j[i]) : null);

            bar.put("zxdq", !Double.isNaN(zxdq[i]) ? round2(zxdq[i]) : null);
            bar.put("zxdkx", !Double.isNaN(zxdkx[i]) ? round2(zxdkx[i]) : null);
        }
    }

    private void calcMA(double[] closes, int n, double[] out) {
        for (int i = 0; i < closes.length; i++) {
            if (i < n - 1) { out[i] = Double.NaN; continue; }
            double sum = 0;
            for (int j = i - n + 1; j <= i; j++) sum += closes[j];
            out[i] = sum / n;
        }
    }

    private void calcMACD(double[] closes, double[] dif, double[] dea, double[] hist) {
        int len = closes.length;
        double[] ema12 = emaOf(closes, 12);
        double[] ema26 = emaOf(closes, 26);
        for (int i = 0; i < len; i++) {
            if (!Double.isNaN(ema12[i]) && !Double.isNaN(ema26[i])) {
                dif[i] = ema12[i] - ema26[i];
            } else {
                dif[i] = Double.NaN;
            }
        }
        // DEA = EMA9 of DIF
        double[] difVals = new double[len];
        int cnt = 0;
        for (int i = 0; i < len; i++) {
            if (!Double.isNaN(dif[i])) difVals[cnt++] = dif[i];
        }
        double[] difCompact = java.util.Arrays.copyOf(difVals, cnt);
        double[] deaCompact = emaOf(difCompact, 9);
        cnt = 0;
        for (int i = 0; i < len; i++) {
            if (!Double.isNaN(dif[i])) {
                dea[i] = deaCompact[cnt++];
                hist[i] = (dif[i] - dea[i]) * 2;
            } else {
                dea[i] = Double.NaN;
                hist[i] = Double.NaN;
            }
        }
    }

    private void calcKDJ(double[] highs, double[] lows, double[] closes,
                         double[] k, double[] d, double[] j) {
        int len = closes.length;
        int n = 9, m1 = 3, m2 = 3;
        for (int i = 0; i < len; i++) {
            if (i < n - 1) { k[i] = d[i] = j[i] = Double.NaN; continue; }
            double hMax = Double.MIN_VALUE, lMin = Double.MAX_VALUE;
            for (int t = i - n + 1; t <= i; t++) {
                if (highs[t] > hMax) hMax = highs[t];
                if (lows[t] < lMin) lMin = lows[t];
            }
            double rsv = (hMax == lMin) ? 50 : (closes[i] - lMin) / (hMax - lMin) * 100;
            double prevK = (i == n - 1) ? 50 : (Double.isNaN(k[i - 1]) ? 50 : k[i - 1]);
            double prevD = (i == n - 1) ? 50 : (Double.isNaN(d[i - 1]) ? 50 : d[i - 1]);
            k[i] = (2.0 / m1) * prevK + (1.0 / m1) * rsv;
            d[i] = (2.0 / m2) * prevD + (1.0 / m2) * k[i];
            j[i] = 3 * k[i] - 2 * d[i];
        }
    }

    private double[] calcZXDQ(double[] closes) {
        int len = closes.length;
        double[] ema10 = emaOf(closes, 10);
        // 提取有效值再算 EMA10
        double[] vals = new double[len];
        int cnt = 0;
        for (int i = 0; i < len; i++) {
            if (!Double.isNaN(ema10[i])) vals[cnt++] = ema10[i];
        }
        double[] compact = java.util.Arrays.copyOf(vals, cnt);
        double[] ema2 = emaOf(compact, 10);
        double[] result = new double[len];
        cnt = 0;
        for (int i = 0; i < len; i++) {
            if (!Double.isNaN(ema10[i])) {
                result[i] = ema2[cnt++];
            } else {
                result[i] = Double.NaN;
            }
        }
        return result;
    }

    private double[] calcZXDKX(double[] closes) {
        int len = closes.length;
        double[] m14 = new double[len]; calcMA(closes, 14, m14);
        double[] m28 = new double[len]; calcMA(closes, 28, m28);
        double[] m57 = new double[len]; calcMA(closes, 57, m57);
        double[] m114 = new double[len]; calcMA(closes, 114, m114);
        double[] result = new double[len];
        for (int i = 0; i < len; i++) {
            if (!Double.isNaN(m14[i]) && !Double.isNaN(m28[i])
                && !Double.isNaN(m57[i]) && !Double.isNaN(m114[i])) {
                result[i] = (m14[i] + m28[i] + m57[i] + m114[i]) / 4;
            } else {
                result[i] = Double.NaN;
            }
        }
        return result;
    }

    /** EMA 数组，前 N-1 个为 NaN */
    private double[] emaOf(double[] arr, int n) {
        int len = arr.length;
        double[] result = new double[len];
        double k = 2.0 / (n + 1);
        for (int i = 0; i < len; i++) {
            if (i < n - 1) { result[i] = Double.NaN; continue; }
            if (i == n - 1) {
                result[i] = arr[i];
            } else {
                result[i] = arr[i] * k + result[i - 1] * (1 - k);
            }
        }
        return result;
    }

    private Double round2(double v) { return Double.isNaN(v) ? null : Math.round(v * 100.0) / 100.0; }
    private Double round4(double v) { return Double.isNaN(v) ? null : Math.round(v * 10000.0) / 10000.0; }

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

}
