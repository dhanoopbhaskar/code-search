package com.example.profile;

import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class ProfileController {

    @PostMapping("/profiles/{username}/follow")
    public void follow(String username) {
    }

    @DeleteMapping("/profiles/{username}/follow")
    public void unfollow(String username) {
    }
}