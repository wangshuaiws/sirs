package com.sirs;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
@MapperScan("com.sirs.mapper")
public class SirsApplication {
    public static void main(String[] args) {
        SpringApplication.run(SirsApplication.class, args);
    }
}
