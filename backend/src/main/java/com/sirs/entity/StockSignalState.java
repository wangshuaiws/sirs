package com.sirs.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.Data;
import java.time.LocalDate;
import java.time.LocalDateTime;

@Data
@TableName("stock_signal_state")
public class StockSignalState {
    @TableId(type = IdType.AUTO)
    private Long id;

    private Long userId;
    private String stockCode;
    private String signalState;
    private LocalDate goldenCrossDate;
    private Boolean whiteBuyNotified;
    private Boolean yellowBuyNotified;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private LocalDateTime updatedAt;
}
