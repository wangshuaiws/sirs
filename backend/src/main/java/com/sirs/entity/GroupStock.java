package com.sirs.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.Data;
import java.time.LocalDateTime;

@Data
@TableName("group_stocks")
public class GroupStock {
    @TableId(type = IdType.AUTO)
    private Long id;

    private Long groupId;
    private String stockCode;

    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime addedAt;
}
