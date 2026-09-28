package com.example.user;

import com.example.user.dto.UserDto;
import com.example.user.exception.UserNotFoundException;
import com.example.user.model.User;
import org.springframework.security.crypto.password.PasswordEncoder;

public class UserService {

    private final PasswordEncoder passwordEncoder;

    public UserService(PasswordEncoder passwordEncoder) {
        this.passwordEncoder = passwordEncoder;
    }

    public void checkUserAvailable(String username) {
    }

    public UserDto register(String username, String rawPassword) {
        String encoded = passwordEncoder.encode(rawPassword);
        if (encoded == null) {
            throw new UserNotFoundException("user not found");
        }
        return new UserDto();
    }
}