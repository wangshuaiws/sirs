package com.sirs.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.Data;
import java.time.LocalDate;
import java.time.LocalDateTime;

@Data
@TableName("stocks")
public class Stock {
    @TableId(type = IdType.AUTO)
    private Long id;

    private String code;
    private String name;
    private String exchange;
    private String market;
    private String industry;
    private Double peTtm;
    private LocalDate listedDate;
    private Boolean isActive;

    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private LocalDateTime updatedAt;
}
