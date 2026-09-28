package com.example.user;

import com.example.user.dto.UserDto;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class UserController {

    @GetMapping("/user")
    public UserDto currentUser() {
        return new UserDto();
    }
}