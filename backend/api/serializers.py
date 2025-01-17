from django.shortcuts import get_object_or_404
from foodgram.models import (FavouriteList, Ingredient, IngredientAmount,
                             Recipe, ShoppingList, Subscription, Tag)
from rest_framework import serializers
from users.models import User

from .fields import Base64ImageField


class CustomUserSerializer(serializers.ModelSerializer):
    """Serializer for users."""

    is_subscribed = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            'email', 'id', 'username', 'first_name',
            'last_name', 'is_subscribed'
        )

    def get_is_subscribed(self, obj):
        user = self.context['request'].user
        if user.is_anonymous:
            return False
        return Subscription.objects.filter(
            author=obj, user=user
        ).exists()


class TagSerializer(serializers.ModelSerializer):
    """Serializer for tags."""

    class Meta:
        model = Tag
        fields = ('id', 'name', 'color', 'slug')


class IngredientSerializer(serializers.ModelSerializer):
    """Serializer for ingredients."""

    class Meta:
        model = Ingredient
        fields = ('id', 'name', 'measurement_unit')
        read_only_fields = ('id', 'name', 'measurement_unit')


class IngredientAmountShowSerializer(serializers.ModelSerializer):
    """Serializer for displaying ingredients with amounts."""

    id = serializers.ReadOnlyField(source='ingredient.id')
    name = serializers.ReadOnlyField(source='ingredient.name')
    measurement_unit = serializers.ReadOnlyField(
        source='ingredient.measurement_unit'
    )

    class Meta:
        model = IngredientAmount
        fields = ('id', 'name', 'measurement_unit', 'amount')


class RecipeReadOnlySerializer(serializers.ModelSerializer):
    """Read only recipe serializer."""

    image = Base64ImageField()

    class Meta:
        model = Recipe
        fields = ('id', 'name', 'image', 'cooking_time')
        read_only_fields = ('id', 'name', 'image', 'cooking_time')


class RecipeViewSerializer(serializers.ModelSerializer):
    """Serializer for displaying recipes."""

    image = Base64ImageField()
    tags = TagSerializer(many=True, read_only=True)
    author = CustomUserSerializer(read_only=True)
    ingredients = serializers.SerializerMethodField()
    is_favorited = serializers.SerializerMethodField()
    is_in_shopping_cart = serializers.SerializerMethodField()

    class Meta:
        model = Recipe
        fields = (
            'id', 'tags', 'author',
            'ingredients', 'is_favorited',
            'is_in_shopping_cart', 'name',
            'image', 'text', 'cooking_time'
        )

    def get_ingredients(self, obj):
        qs = IngredientAmount.objects.filter(recipe=obj)
        return IngredientAmountShowSerializer(qs, many=True).data

    def get_is_favorited(self, obj):
        user = self.context['request'].user
        if user.is_anonymous:
            return False
        return FavouriteList.objects.filter(
            user=user, recipe_id=obj.id
        ).exists()

    def get_is_in_shopping_cart(self, obj):
        user = self.context['request'].user
        if user.is_anonymous:
            return False
        return ShoppingList.objects.filter(
            user=user, recipe_id=obj.id
        ).exists()


class IngredientAddToRecipeSerializer(serializers.ModelSerializer):
    """Serializer to add ingredients to a recipe."""

    id = serializers.PrimaryKeyRelatedField(queryset=Ingredient.objects.all())
    amount = serializers.IntegerField()

    class Meta:
        model = IngredientAmount
        fields = ('id', 'amount')


class RecipeCreateUpdateSerializer(serializers.ModelSerializer):
    """Serializer to create or update recipes."""

    tags = serializers.PrimaryKeyRelatedField(
        queryset=Tag.objects.all(), many=True
    )
    author = CustomUserSerializer(read_only=True)
    ingredients = IngredientAddToRecipeSerializer(many=True)
    cooking_time = serializers.IntegerField()
    image = Base64ImageField()

    class Meta:
        model = Recipe
        fields = (
            'id', 'tags', 'author', 'ingredients',
            'name', 'image', 'text', 'cooking_time'
        )

    def validate_ingredients(self, data):
        if not data:
            raise serializers.ValidationError(
                'Нужен хотя бы один ингредиент.'
            )
        if len(data) != len(set([i['id'] for i in data])):
            raise serializers.ValidationError(
                'Ингредиенты должы быть уникальными.'
            )
        for ingredient in data:
            if ingredient['amount'] <= 0:
                raise serializers.ValidationError(
                    'Количество должно быть больше нуля.'
                )
        return data

    def validate_tags(self, data):
        if not data:
            raise serializers.ValidationError('Нужен хотя бы один тег.')
        if len(data) != len(set(data)):
            raise serializers.ValidationError(
                'Теги должны быть уникальными.'
            )
        return data

    def validate_cooking_time(self, data):
        if not isinstance(data, int):
            raise serializers.ValidationError(
                'Неверный формат, ожидается целое позитивное число.'
            )
        if data <= 0:
            raise serializers.ValidationError(
                'Минимальное время готовки должно быть больше нуля'
            )
        return data

    def add_ingredients(self, ingredients, recipe):
        for ing in ingredients:
            ing_id = ing.get('id')
            IngredientAmount.objects.create(
                recipe=recipe,
                ingredient=ing_id,
                amount=ing.get('amount')
            )

    def create(self, validated_data):
        ingredients = validated_data.pop('ingredients')
        tags = validated_data.pop('tags')
        image = validated_data.pop('image')
        new_recipe = Recipe.objects.create(image=image, **validated_data)
        self.add_ingredients(ingredients, new_recipe)
        new_recipe.tags.set(tags)
        return new_recipe

    def update(self, instance, validated_data):
        instance.last_editor = validated_data.pop(
            'last_editor', self.context['request'].user
        )
        tags_data = validated_data.pop('tags')
        ingredients = validated_data.pop('ingredients')
        super().update(instance, validated_data)
        if tags_data:
            instance.tags.set(tags_data)
        if ingredients:
            instance.ingredients.clear()
            self.add_ingredients(ingredients, instance)
        return instance

    def to_representation(self, instance):
        return RecipeViewSerializer(
            instance, context={
                'request': self.context.get('request')
            }).data


class FavouriteListSerializer(serializers.ModelSerializer):
    """Serializer for list of favourite recipes."""

    class Meta:
        model = FavouriteList
        fields = ('id',)

    def to_representation(self, instance):
        return RecipeReadOnlySerializer(
            instance.recipe, context={
                'request': self.context.get('request')
            }).data

    def create(self, validated_data):
        recipe_id = self.context.get(
            'request'
        ).parser_context.get('kwargs').get('recipe_id')
        recipe = get_object_or_404(Recipe, id=recipe_id)
        user = self.context['request'].user
        validated_data['recipe'] = recipe
        validated_data['user'] = user
        return super().create(validated_data)


class ShoppingListSerializer(FavouriteListSerializer):
    """Serializer for shopping list."""

    class Meta:
        model = ShoppingList
        fields = ('id',)


class SubscriptionSerializer(serializers.ModelSerializer):
    """Serializer for subscribtions."""

    id = serializers.ReadOnlyField(source='author.id')
    email = serializers.ReadOnlyField(source='author.email')
    username = serializers.ReadOnlyField(source='author.username')
    first_name = serializers.ReadOnlyField(source='author.first_name')
    last_name = serializers.ReadOnlyField(source='author.last_name')
    is_subscribed = serializers.SerializerMethodField()
    recipes = serializers.SerializerMethodField()
    recipes_count = serializers.SerializerMethodField()

    class Meta:
        model = Subscription
        fields = (
            'id', 'email', 'username', 'first_name',
            'last_name', 'is_subscribed', 'recipes',
            'recipes_count'
        )

    def get_recipes_count(self, obj):
        return obj.author.foodgram_recipe_authors.count()

    def get_recipes(self, obj):
        recipes_limit = self.context.get(
            'request'
        ).query_params.get('recipes_limit')
        try:
            recipes_limit = int(recipes_limit)
        except (TypeError, ValueError):
            recipes_limit = None
        qs = obj.author.foodgram_recipe_authors.all()
        if recipes_limit:
            qs = qs[:recipes_limit]
        return RecipeReadOnlySerializer(
            qs, many=True, context=self.context
        ).data

    def get_is_subscribed(self, obj):
        return Subscription.objects.filter(
            user=obj.user,
            author=obj.author
        ).exists()

    def get_user_and_author(self):
        kwargs = self.context.get('request').parser_context.get('kwargs')
        author = get_object_or_404(User, pk=kwargs.get('author_id'))
        user = self.context.get('request').user
        return user, author

    def validate(self, attrs):
        user, author = self.get_user_and_author()
        if user == author:
            raise serializers.ValidationError(
                {'errors': 'Нельзя подписаться на себя!'}
            )
        elif user.follower.filter(
                author=author).exists():
            raise serializers.ValidationError(
                {'errors': 'Вы уже подписаны на этого пользователя!'},
            )
        return {'user': user, 'author': author}
