#include <string>

class OrderService {
public:
    std::string save(const std::string& order) {
        return repository_ + order;
    }

private:
    std::string repository_;
};

int free_helper(int value) {
    return value + 1;
}
