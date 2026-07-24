package com.sirs.service;

import java.util.List;
import java.util.Map;

public interface KlineService {
    List<Map<String, Object>> getKline(String code, String period, String from, String to, boolean adjusted);
}
