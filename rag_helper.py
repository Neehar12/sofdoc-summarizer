def l2_dist(query_embedding, resource_embedding):
    dist = 0
    for i in range(len(query_embedding)):
        dist += (query_embedding[i] - resource_embedding[i])*(query_embedding[i] - resource_embedding[i])
    return dist

def search(query_embedding, embedding_array, resource_array):
    top_n = 10
    dist_array = []
    for embedding in embedding_array:
        dist_array.append(l2_dist(query_embedding, embedding))
    dist_array.sort()
    if len(dist_array) > top_n:
        threshold = dist_array[top_n - 1]
    else:
        threshold = dist_array[:-1]
    related_resources = []
    count = 0
    for i in range(len(dist_array)):
        if dist_array[i] > threshold:
            continue
        related_resources.append(resource_array[i])
        count += 1
        if count > top_n:
            break
    print(count)
    return related_resources