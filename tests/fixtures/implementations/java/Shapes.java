package fixtures;

interface Animal {
    void speak(String sound);
}

class Dog implements Animal {
    public void speak(String sound) {
    }
}

abstract class AbstractPet implements Animal {
    public void speak(String sound) {
    }
}

class Puppy extends AbstractPet {
}

interface Pet extends Animal {
    void speak(String sound);
}

class Cat implements Pet {
    public void speak(String sound) {
    }
}

interface Repository {
    Object find(String key);
}

interface Alpha {
    void handle();
}

interface Beta {
    void handle();
}

class Multi implements Alpha, Beta {
    public void handle() {
    }
}

interface Calculator {
    int add(int a, int b);

    String add(String a, String b);
}

class CalculatorImpl implements Calculator {
    public int add(int a, int b) {
        return a + b;
    }

    public String add(String a, String b) {
        return a;
    }
}

class Outer {
    static class InnerAnimal implements Animal {
        public void speak(String sound) {
        }
    }
}

class Zoo {
    Animal make() {
        return new Animal() {
            public void speak(String sound) {
            }
        };
    }
}
