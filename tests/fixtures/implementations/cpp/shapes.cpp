class Animal {
 public:
  virtual void speak(int sound) {}
};

class Dog : public Animal {
 public:
  void speak(int sound) override {}
};

class Pet : public Animal {
 public:
  virtual void speak(int sound) {}
};

class Cat : public Pet {
 public:
  void speak(int sound) override {}
};

class Repository {
 public:
  virtual void find(int key) {}
};
