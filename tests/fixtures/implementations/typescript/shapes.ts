interface Animal {
  speak(sound: string): void;
}

class Dog implements Animal {
  speak(sound: string): void {}
}

interface Pet extends Animal {
  speak(sound: string): void;
}

class Cat implements Pet {
  speak(sound: string): void {}
}

interface Repository {
  find(key: string): unknown;
}
