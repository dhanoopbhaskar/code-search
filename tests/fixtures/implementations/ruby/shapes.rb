class Animal
  def speak(sound)
    sound
  end
end

class Dog < Animal
  def speak(sound)
    sound
  end
end

class Pet < Animal
  def speak(sound)
    sound
  end
end

class Cat < Pet
  def speak(sound)
    sound
  end
end

class Repository
  def find(key)
    key
  end
end
