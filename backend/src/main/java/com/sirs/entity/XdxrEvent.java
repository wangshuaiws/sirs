package com.sirs.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.Data;
import java.time.LocalDate;
import java.time.LocalDateTime;

@Data
@TableName("xdxr_events")
public class XdxrEvent {
    @TableId(type = IdType.AUTO)
    private Long id;

    private String code;
    private LocalDate exDate;
    private Integer category;
    private Double fenhong;
    private Double songzhuangu;
    private Double peigu;
    private Double peigujia;

    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createdAt;
}
