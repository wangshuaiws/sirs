package com.sirs.dto;

import lombok.Data;

@Data
public class NotificationQuery {
    private String type;
    private String keyword;
    private String dateFrom;
    private String dateTo;
    private int page = 1;
    private int size = 20;
}
