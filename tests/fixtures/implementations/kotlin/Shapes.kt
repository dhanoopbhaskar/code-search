interface Animal {
    fun speak(sound: String)
}

class Dog : Animal {
    override fun speak(sound: String) {}
}

interface Pet : Animal {
    fun speak(sound: String)
}

class Cat : Pet {
    override fun speak(sound: String) {}
}

interface Repository {
    fun find(key: String)
}
