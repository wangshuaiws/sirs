package com.sirs.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.sirs.entity.Notification;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;
import java.util.Map;

@Mapper
public interface NotificationMapper extends BaseMapper<Notification> {

    @Select("SELECT type, COUNT(*) as count FROM notifications WHERE user_id = #{userId} GROUP BY type")
    List<Map<String, Object>> countByType(@Param("userId") Long userId);

    @Select("SELECT type, COUNT(*) as count FROM notifications WHERE user_id = #{userId} AND is_read = FALSE GROUP BY type")
    List<Map<String, Object>> countUnreadByType(@Param("userId") Long userId);
}
