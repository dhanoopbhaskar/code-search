package com.example.auth;

import com.example.user.dto.UserDto;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class AuthController {

    @PostMapping("/login")
    public UserDto login(String username, String password) {
        return new UserDto();
    }
}