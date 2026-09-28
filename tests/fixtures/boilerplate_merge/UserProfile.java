import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * A user profile in the identity service.
 */
public class UserProfile {
    private Long id;
    private String name;
    private String email;
    private List<String> roles;

    public UserProfile(Long id, String name) {
        this.id = id;
        this.name = name;
    }

    public Long getId() {
        return id;
    }

    public String getName() {
        return name;
    }

    public void refresh() {
        trigger();
        cache = build();
    }
}
