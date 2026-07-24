package com.sirs.config;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.sirs.entity.StockGroup;
import com.sirs.entity.User;
import com.sirs.mapper.StockGroupMapper;
import com.sirs.mapper.UserMapper;
import com.sirs.service.GroupService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.CommandLineRunner;
import org.springframework.stereotype.Component;
import org.springframework.util.DigestUtils;

import java.nio.charset.StandardCharsets;

/**
 * 开发环境：启动时自动创建默认用户和自选股分组。
 * 生产环境应删除此文件或用 profile 隔离。
 */
@Component
public class DataInitializer implements CommandLineRunner {

    private static final Logger log = LoggerFactory.getLogger(DataInitializer.class);

    private static final String DEFAULT_USERNAME = "admin";
    private static final String DEFAULT_PASSWORD = "admin123";
    private static final String DEFAULT_GROUP = "自选股";

    private final UserMapper userMapper;
    private final GroupService groupService;
    private final StockGroupMapper groupMapper;

    public DataInitializer(UserMapper userMapper, GroupService groupService,
                           StockGroupMapper groupMapper) {
        this.userMapper = userMapper;
        this.groupService = groupService;
        this.groupMapper = groupMapper;
    }

    @Override
    public void run(String... args) {
        // 1. 创建或修复默认用户
        User user = userMapper.selectOne(
                new LambdaQueryWrapper<User>().eq(User::getUsername, DEFAULT_USERNAME));
        String salt = "sirs";
        String first = DigestUtils.md5DigestAsHex(
                (DEFAULT_PASSWORD + salt).getBytes(StandardCharsets.UTF_8));
        String correctHash = DigestUtils.md5DigestAsHex(
                (first + salt).getBytes(StandardCharsets.UTF_8));

        if (user == null) {
            user = new User();
            user.setUsername(DEFAULT_USERNAME);
            user.setPasswordHash(correctHash);
            user.setStatus(1);
            userMapper.insert(user);
            log.info("[Init] 默认用户已创建: {} / {}", DEFAULT_USERNAME, DEFAULT_PASSWORD);
        } else if (!correctHash.equals(user.getPasswordHash())) {
            // 修复旧数据：更新为正确的密码哈希
            user.setPasswordHash(correctHash);
            userMapper.updateById(user);
            log.info("[Init] 默认用户密码已修复: {}", DEFAULT_USERNAME);
        } else {
            log.info("[Init] 默认用户已存在: {}", DEFAULT_USERNAME);
        }

        // 2. 创建默认自选股分组
        Long count = groupMapper.selectCount(
                new LambdaQueryWrapper<StockGroup>()
                        .eq(StockGroup::getUserId, user.getId())
                        .eq(StockGroup::getName, DEFAULT_GROUP));
        if (count == 0) {
            groupService.createGroup(user.getId(), DEFAULT_GROUP, "默认自选股分组");
            log.info("[Init] 默认自选股分组已创建");
        }
    }
}
