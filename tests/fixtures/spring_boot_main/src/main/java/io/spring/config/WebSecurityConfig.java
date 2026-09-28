package io.spring.config;

import org.springframework.context.annotation.Configuration;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;

@Configuration
@EnableWebSecurity
public class WebSecurityConfig {

  public void configureSecurityRules() {
    // request authorization rules for the article API
  }
}
