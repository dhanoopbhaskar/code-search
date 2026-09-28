public class SampleClass {
    private String name;

    public SampleClass(String name) {
        this.name = name;
    }

    public void handle(int value) {
    }

    public void handle(String text) {
    }

    public void process() {
    }

    public static class InnerClass {
        public int count;
    }

    public enum Status {
        ACTIVE, INACTIVE
    }

    public interface Callback {
        void onEvent();
    }
}
