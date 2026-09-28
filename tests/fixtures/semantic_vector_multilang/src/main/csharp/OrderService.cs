namespace Multi {
    public class OrderService {
        private readonly string repository;

        public OrderService(string repository) {
            this.repository = repository;
        }

        public string Save(string order) {
            return repository + order;
        }
    }
}
