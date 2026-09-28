namespace Fixtures;

interface Animal
{
    void Speak(string sound);
}

class Dog : Animal
{
    public void Speak(string sound)
    {
    }
}

interface Pet : Animal
{
    void Speak(string sound);
}

class Cat : Pet
{
    public void Speak(string sound)
    {
    }
}

interface Repository
{
    object Find(string key);
}
